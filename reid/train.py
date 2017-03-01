from __future__ import print_function
import time

from torch.autograd import Variable

from .evaluation import accuracy, cmc
from .loss.oim import OIMLoss
from .metrics import pairwise_distance
from .utils.meters import AverageMeter


class Trainer(object):
    def __init__(self, model, criterion, args):
        super(Trainer, self).__init__()
        self.model = model
        self.criterion = criterion
        self.args = args

    def train(self, epoch, data_loader, optimizer):
        batch_time = AverageMeter()
        data_time = AverageMeter()
        losses = AverageMeter()
        top1 = AverageMeter()

        self.model.train()

        end = time.time()
        for i, (imgs, _, pids, _) in enumerate(data_loader):
            data_time.update(time.time() - end)

            pids = pids.cuda()
            inputs = Variable(imgs)
            targets = Variable(pids)

            outputs = self.model(inputs)
            if isinstance(self.criterion, OIMLoss):
                loss, outputs = self.criterion(outputs, targets)
            else:
                loss = self.criterion(outputs, targets)
            prec1, = accuracy(outputs.data, pids)
            losses.update(loss.data[0], imgs.size(0))
            top1.update(prec1[0], imgs.size(0))

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            batch_time.update(time.time() - end)
            end = time.time()

            if (i + 1) % self.args.print_freq == 0:
                print('Epoch: [{}][{}/{}]\t'
                      'Time {:.3f} ({:.3f})\t'
                      'Data {:.3f} ({:.3f})\t'
                      'Loss {:.3f} ({:.3f})\t'
                      'Top1 {:.2%} ({:.2%})\t'.format(
                    epoch, i + 1, len(data_loader),
                    batch_time.val, batch_time.avg,
                    data_time.val, data_time.avg,
                    losses.val, losses.avg, top1.val, top1.avg))


class Evaluator(object):
    def __init__(self, model, args):
        super(Evaluator, self).__init__()
        self.model = model
        self.args = args

    def evaluate(self, data_loader, query, gallery):
        features = self.extract_features(data_loader)
        distmat = pairwise_distance(features, query, gallery)

        query_ids = [pid for _, pid, _ in query]
        gallery_ids = [pid for _, pid, _ in gallery]
        query_cams = [cam for _, _, cam in query]
        gallery_cams = [cam for _, _, cam in gallery]

        # Compute both new and old cmc scores
        cmc_configs = {
            'new': dict(separate_camera_set=False,
                        single_gallery_shot=False,
                        first_match_break=False),
            'cuhk03': dict(separate_camera_set=True,
                           single_gallery_shot=True,
                           first_match_break=False),
            'market1501': dict(separate_camera_set=False,
                               single_gallery_shot=False,
                               first_match_break=True),
        }
        cmc_scores = {name: cmc(distmat, query_ids, gallery_ids,
                                query_cams, gallery_cams, **params)
                      for name, params in cmc_configs.items()}

        print('CMC Scores{:>12}{:>12}{:>12}'
              .format('new', 'cuhk03', 'market1501'))
        for k in [1, 5, 10]:
            print('  top-{:<4}{:12.1%}{:12.1%}{:12.1%}'
                  .format(k, cmc_scores['new'][k-1], cmc_scores['cuhk03'][k-1],
                          cmc_scores['market1501'][k-1]))

        # Use the new cmc top-1 score for validation criterion
        return cmc_scores['new'][0]

    def extract_features(self, data_loader):
        self.model.eval()

        features = {}

        batch_time = AverageMeter()
        data_time = AverageMeter()

        end = time.time()
        for i, (imgs, fnames, _, _) in enumerate(data_loader):
            data_time.update(time.time() - end)

            inputs = Variable(imgs, volatile=True)
            outputs = self.model(inputs).data

            assert len(fnames) == outputs.size(0)
            for fname, output in zip(fnames, outputs):
                features[fname] = output

            batch_time.update(time.time() - end)
            end = time.time()

            if (i + 1) % self.args.print_freq == 0:
                print('Evaluate: [{}/{}]\t'
                      'Time {:.3f} ({:.3f})\t'
                      'Data {:.3f} ({:.3f})\t'.format(
                    i + 1, len(data_loader),
                    batch_time.val, batch_time.avg,
                    data_time.val, data_time.avg))

        return features